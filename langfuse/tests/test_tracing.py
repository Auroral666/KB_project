"""Behavior checks for streaming, parenting, usage, redaction and fail-open tracing."""
import contextvars
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from kb_observability import tracing


class FakeSpan:
    def __init__(self, number, options, client, parent=None):
        self.id = f"{number:016x}"
        self.options = options
        self.client = client
        self.parent = parent
        self.trace_id = parent.trace_id if parent else uuid4().hex
        self.updates = {}
        self.ended = False

    def update(self, **fields):
        self.updates.update(fields)

    def end(self):
        self.ended = True

    def start_observation(self, **options):
        return self.client.add(options, parent=self)


class FakeClient:
    def __init__(self):
        self.spans = []

    def start_observation(self, **options):
        return self.add(options)

    def add(self, options, parent=None):
        span = FakeSpan(len(self.spans) + 1, options, self, parent)
        self.spans.append(span)
        return span


class TracingTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeClient()
        self.environment = patch.dict(os.environ, {"LANGFUSE_ENABLED": "true", "LANGFUSE_CAPTURE_CONTENT": "true"})
        self.environment.start()
        self.sdk = patch.object(tracing, "client", return_value=self.fake)
        self.sdk.start()

    def tearDown(self):
        self.sdk.stop()
        self.environment.stop()
        self.assertIsNone(tracing.current.get())

    def test_nested_observations_share_trace_and_have_correct_parent(self):
        child = tracing.observe(lambda text: text.upper(), "retrieve")
        root = tracing.observe(lambda text: child(text), "chat")
        self.assertEqual(root("question"), "QUESTION")
        parent, nested = self.fake.spans
        self.assertEqual(parent.trace_id, nested.trace_id)
        self.assertIsNone(parent.parent)
        self.assertIs(nested.parent, parent)
        self.assertTrue(all(s.ended for s in self.fake.spans))

    def test_sse_iteration_in_different_contexts_keeps_parent_and_restores_context(self):
        child = tracing.observe(lambda: "part", "child")
        def stream():
            yield child()
            yield child()
        iterator = tracing.observe(stream, "stream")()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(pool.submit(contextvars.Context().run, next, iterator).result(), "part")
            self.assertEqual(pool.submit(contextvars.Context().run, next, iterator).result(), "part")
            with self.assertRaises(StopIteration):
                pool.submit(contextvars.Context().run, next, iterator).result()
        root = self.fake.spans[0]
        self.assertTrue(root.ended)
        self.assertTrue(all(s.parent is root for s in self.fake.spans[1:]))

    def test_sdk_failure_never_changes_business_result(self):
        self.fake.start_observation = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
        function = tracing.observe(lambda: {"answer": "still works"}, "chat")
        self.assertEqual(function(), {"answer": "still works"})

    def test_error_event_is_marked_as_error_without_modifying_it(self):
        error = {"type": "error", "message": "回答未完成"}
        def source():
            yield {"type": "delta", "text": "partial"}
            yield error
        self.assertEqual(list(tracing.observe(source, "chat")())[-1], error)
        self.assertEqual(self.fake.spans[0].updates["level"], "ERROR")
        self.assertTrue(self.fake.spans[0].ended)

    def test_cancelled_generator_is_closed(self):
        def source():
            yield "partial"
            yield "second"
        iterator = tracing.observe(source, "chat")()
        self.assertEqual(next(iterator), "partial")
        iterator.close()
        self.assertTrue(self.fake.spans[0].ended)
        self.assertTrue(self.fake.spans[0].updates["metadata"]["cancelled"])

    def test_generation_records_first_nonempty_text_and_provider_usage(self):
        options = {}
        def source(messages, **kwargs):
            options.update(kwargs)
            yield SimpleNamespace(content="", usage_metadata=None, response_metadata={})
            yield SimpleNamespace(content="answer", usage_metadata=None, response_metadata={})
            yield SimpleNamespace(content="", usage_metadata={"input_tokens": 11, "output_tokens": 4, "total_tokens": 15}, response_metadata={})
        stream = tracing.observe(source, "generation", kind="generation", generation=True, model="test")
        result = list(stream([("human", "question")]))
        self.assertEqual(result[1].content, "answer")
        recorded = self.fake.spans[0].updates
        self.assertTrue(options["stream_usage"])
        self.assertIn("completion_start_time", recorded)
        self.assertEqual(recorded["usage_details"], {"input": 11, "output": 4, "total": 15})
        self.assertEqual(recorded["output"], "answer")

    def test_payload_masks_secrets_and_summarizes_vectors(self):
        with patch.dict(os.environ, {"TEST_API_KEY": "private-test-value"}):
            result = tracing.sanitize({"text": "private-test-value", "api_key": "hidden", "vector": list(range(100))})
        self.assertEqual(result["text"], "[REDACTED]")
        self.assertEqual(result["api_key"], "[REDACTED]")
        self.assertEqual(result["vector"]["dimensions"], 100)
        self.assertEqual(tracing.sanitize(data={"x": 1}), {"x": 1})

    def test_disabled_instrumentation_passes_through(self):
        with patch.dict(os.environ, {"LANGFUSE_ENABLED": "false"}):
            self.assertEqual(tracing.observe(lambda x: x, "noop")(12), 12)
        self.assertEqual(self.fake.spans, [])

    def test_content_capture_can_be_disabled_while_timing_remains(self):
        with patch.dict(os.environ, {"LANGFUSE_CAPTURE_CONTENT": "false"}):
            self.assertEqual(tracing.observe(lambda text: text, "chat")("question"), "question")
        self.assertNotIn("input", self.fake.spans[0].options)
        self.assertNotIn("output", self.fake.spans[0].updates)
        self.assertIn("observed_duration_ms", self.fake.spans[0].updates["metadata"])
