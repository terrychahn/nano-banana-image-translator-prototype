import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
import io
from evaluator import evaluate_translation

class TestEvaluator(unittest.TestCase):
    def test_evaluate_translation_true(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [MagicMock()]
        mock_response.candidates[0].content.parts[0].text = "True"
        mock_client.models.generate_content.return_value = mock_response

        orig_img = Image.new('RGB', (100, 100))
        trans_img = Image.new('RGB', (100, 100))
        
        result, details = evaluate_translation(mock_client, orig_img, trans_img, "Evaluate this")
        self.assertTrue(result)
        self.assertEqual(details, "True")

    def test_evaluate_translation_false(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        mock_response.candidates[0].content.parts = [MagicMock()]
        mock_response.candidates[0].content.parts[0].text = "False"
        mock_client.models.generate_content.return_value = mock_response

        orig_img = Image.new('RGB', (100, 100))
        trans_img = Image.new('RGB', (100, 100))
        
        result, details = evaluate_translation(mock_client, orig_img, trans_img, "Evaluate this")
        self.assertFalse(result)
        self.assertEqual(details, "False")

if __name__ == '__main__':
    unittest.main()
