"""Smoke and behavior checks for the local RAG implementation."""
import unittest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.main import INDEX, AskRequest, Chunk, GeminiUnavailableError, ask, current_revision, llm_answer, retrieve


class CopilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pass

    @patch("app.main.llm_answer", return_value="Generated grounded test answer.")
    def ask(self, question, _mock_llm):
        return ask(AskRequest(question=question))

    def test_index_contains_all_three_operational_documents(self):
        ids = {c.document_id for c in INDEX}
        self.assertTrue({"MNT-MAN-CNC-02", "SAF-SOP-003", "QC-SOP-014"}.issubset(ids))

    def test_current_qc_revision_is_four(self):
        self.assertEqual(current_revision(INDEX)["QC-SOP-014"], "04")

    def test_alarm_answer_cites_manual(self):
        data = self.ask("What does alarm AL-104 mean and what should the operator do?")
        self.assertFalse(data["abstained"])
        self.assertTrue(any(s["document_id"] == "MNT-MAN-CNC-02" for s in data["sources"]))

    def test_lot_of_100_uses_revision_four(self):
        data = self.ask("For a lot of 100 pieces, how many samples should QC inspect?")
        self.assertFalse(data["abstained"])
        self.assertTrue(any(s["document_id"] == "QC-SOP-014" and s["revision"] == "04" for s in data["sources"]))
        self.assertFalse(any(s["document_id"] == "QC-SOP-014" and s["revision"] == "03" for s in data["sources"]))

    def test_regression_lot_100_retrieves_rev04_sampling_plan_page_one(self):
        question = "For an incoming material lot containing 100 pieces, how many samples should the QC inspector inspect according to the latest procedure?"
        retrieved = retrieve(question)
        sampling_plan = [
            chunk for chunk, _ in retrieved
            if chunk.document_id == "QC-SOP-014" and chunk.revision == "04"
            and chunk.page == 1 and "91 - 500" in chunk.text and "13" in chunk.text
        ]
        self.assertTrue(sampling_plan, "Retrieval should return Rev 04 Page 1 with the 91–500 row and its 13-sample value.")
        data = self.ask(question)
        self.assertFalse(data["abstained"])
        self.assertTrue(any(s["document_id"] == "QC-SOP-014" and s["revision"] == "04" and s["page"] == 1 for s in data["sources"]))

    def test_salary_question_abstains(self):
        data = self.ask("What is the factory supervisor's salary?")
        self.assertTrue(data["abstained"])

    def test_all_evaluation_questions_retrieve_expected_sources_or_abstain(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / "evaluation_questions.json").read_text())
        for case in cases["provided_sample_questions"] + cases["additional_questions"]:
            with self.subTest(question=case["question"]), patch(
                "app.main.llm_answer", return_value="Test-only generated response."
            ):
                data = ask(AskRequest(question=case["question"]))
                if case.get("unanswerable"):
                    self.assertTrue(data["abstained"])
                else:
                    self.assertFalse(data["abstained"])
                    self.assertTrue(any(
                        source["document_id"] == case["document"]
                        and source["revision"] == case["revision"]
                        for source in data["sources"]
                    ))

    def test_answer_includes_page_metadata(self):
        data = self.ask("What is the recommended coolant concentration for the TX-200?")
        self.assertTrue(data["sources"])
        self.assertTrue(all(isinstance(s["page"], int) and s["page"] > 0 for s in data["sources"]))
        self.assertTrue(any("6 - 8" in s["excerpt"] for s in data["sources"]))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-test"}, clear=True)
    @patch("app.main.urllib.request.urlopen")
    def test_gemini_native_interactions_request(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"steps":[{"type":"model_output","content":[{"type":"text","text":"Grounded answer."}]}]}'
        urlopen.return_value = response
        chunk = Chunk("Supported evidence.", "DOC-1", "01", 2, "Test doc", [])
        answer = llm_answer("Question?", [(chunk, 0.9)])
        self.assertEqual(answer, "Grounded answer.")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertIn(b'"model": "gemini-test"', request.data)
        self.assertIn(b"Supported evidence.", request.data)
        self.assertIn(b"DOC-1, Rev 01, p. 2", request.data)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_key_is_explicit(self):
        chunk = Chunk("Supported evidence.", "DOC-1", "01", 2, "Test doc", [])
        with self.assertRaisesRegex(GeminiUnavailableError, "GEMINI_API_KEY"):
            llm_answer("Question?", [(chunk, 0.9)])

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True)
    @patch("app.main.urllib.request.urlopen")
    def test_gemini_api_error_is_not_silenced(self, urlopen):
        from urllib.error import HTTPError
        urlopen.side_effect = HTTPError("https://example.invalid", 401, "unauthorized", {}, None)
        chunk = Chunk("Supported evidence.", "DOC-1", "01", 2, "Test doc", [])
        with self.assertRaisesRegex(GeminiUnavailableError, "HTTP 401"):
            llm_answer("Question?", [(chunk, 0.9)])


if __name__ == "__main__":
    unittest.main()
