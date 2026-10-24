import multiprocessing
import unittest
from unittest.mock import Mock, patch

from captioner_cli import draft_jobs


class DraftJobTests(unittest.TestCase):
    def test_worker_reports_real_progress_then_result(self):
        events = Mock()

        def transcribe(*args, **kwargs):
            kwargs["progress_callback"](12, 30)
            return "Aaj hum", "hi"

        with patch.object(draft_jobs, "transcribe_draft", side_effect=transcribe):
            draft_jobs._worker(events, "clip.wav", "small", "hi")
        self.assertEqual(events.put.call_args_list[1].args[0], ("progress", (12, 30)))
        self.assertEqual(events.put.call_args_list[2].args[0], ("result", "Aaj hum"))

    def test_cancel_terminates_actual_process_and_is_session_scoped(self):
        # An idle worker stands in for an inference call that has not returned yet.
        context = multiprocessing.get_context("spawn")
        wait = context.Event()
        job = draft_jobs.DraftJob("unused.wav", "small", "hi")
        job.process = context.Process(target=wait.wait)
        job.process.start()
        draft_jobs._jobs["test-session"] = job
        try:
            draft_jobs.cancel_draft("different-session")
            self.assertTrue(job.process.is_alive())
            draft_jobs.cancel_draft("test-session")
            self.assertFalse(job.process.is_alive())
            self.assertTrue(job.cancelled.is_set())
            draft_jobs.cancel_draft("test-session")
        finally:
            job.stop()
            job.events.close()
            draft_jobs._jobs.pop("test-session", None)
