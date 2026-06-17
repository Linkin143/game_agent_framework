# core/__init__.py
from .screen_capture  import ScreenCapturer, ScreenCapture
from .ocr_engine      import OCREngine, OCRResult, OCRWord
from .xml_extractor   import XMLExtractor, XMLExtractionResult, UIElement
from .image_analyzer  import ImageAnalyzer, TemplateMatch
from .action_executor import ActionExecutor, ActionResult
