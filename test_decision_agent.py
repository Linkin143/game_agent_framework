from pathlib import Path
import base64
from dotenv import load_dotenv
load_dotenv()

from core.llm.llm_service import LiteLLMService
from agents.decision_agent import DecisionAgent


# ------------------------------------------------------------------
# Fake OCR objects
# ------------------------------------------------------------------

class OCRWord:
    def __init__(self):
        self.text = "PLAY"
        self.center = (500, 400)
        self.confidence = 0.95
        self.bbox = (450, 370, 550, 430)


class OCRResult:
    def __init__(self):
        self.words = [OCRWord()]


# ------------------------------------------------------------------
# Load image
# ------------------------------------------------------------------

img_b64 = base64.b64encode(
    Path("companylogo.png").read_bytes()
).decode()

# ------------------------------------------------------------------
# Fake perception
# ------------------------------------------------------------------

class FakePerception:
    screenshot_b64 = img_b64
    annotated_b64 = img_b64
    registry_annotated_b64 = img_b64

    rendering_engine = "UNITY"

    screen_w = 1080
    screen_h = 1920

    screenshot_source = "test"

    animation_score = 0.0
    is_stable = True

    element_count = 0
    selector_map = []

    ocr_result = OCRResult()
    all_text = "PLAY"

    element_registry = []
    registry_text = ""

    def get_element(self, element_id):
        return None


# ------------------------------------------------------------------
# Azure LLM
# ------------------------------------------------------------------

llm = LiteLLMService(
    model="azure/gpt-5.4"
)

agent = DecisionAgent(llm)

plan = agent.decide(
    perception=FakePerception(),
    current_subgoal="START_GAMEPLAY",
    goal="Launch game and start gameplay"
)

print(type(plan))
print()
print("ACTION :", plan.action_type)
print("TARGET :", plan.target_description)
print("CONF   :", plan.confidence)
print("LOCS   :", plan.locators)
print("REASON :", plan.reasoning[:200])