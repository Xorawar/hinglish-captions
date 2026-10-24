"""Isolated draft workers: real progress and cancellation of model inference."""
import multiprocessing
from queue import Empty
import threading

from .local_workflow import transcribe_draft

_jobs = {}
_lock = threading.Lock()


def _worker(events, media, model, language):
    try:
        events.put(("stage", "Loading the model and preparing audio. First use may download model files."))

        def progress(current, total):
            events.put(("progress", (current, total)))

        text, _ = transcribe_draft(media, model_name=model, language=language,
                                   progress_callback=progress)
        events.put(("result", text))
    except Exception as error:
        events.put(("error", str(error)))


class DraftJob:
    def __init__(self, media, model, language):
        context = multiprocessing.get_context("spawn")
        self.events = context.Queue()
        self.process = context.Process(target=_worker, args=(self.events, media, model, language), daemon=True)
        self.cancelled = threading.Event()
        self._stop_lock = threading.Lock()

    def stop(self):
        with self._stop_lock:
            self.cancelled.set()
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)


def cancel_draft(session):
    with _lock:
        job = _jobs.get(session)
    if job is not None:
        job.stop()


def stream_draft(session, media, model, language):
    job = DraftJob(media, model, language)
    with _lock:
        if session in _jobs:
            raise ValueError("A draft is already running. Cancel it before starting another.")
        job.process.start()
        _jobs[session] = job
    try:
        while not job.cancelled.is_set():
            try:
                event = job.events.get(timeout=.2)
            except Empty:
                if not job.process.is_alive():
                    raise RuntimeError("The draft worker stopped unexpectedly. Try a smaller model.")
                continue
            if job.cancelled.is_set():
                return
            yield event
            if event[0] in ("result", "error"):
                return
    finally:
        job.stop()
        job.events.close()
        with _lock:
            if _jobs.get(session) is job:
                del _jobs[session]
