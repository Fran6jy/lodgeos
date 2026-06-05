"""
Regression accuracy gate.

Runs the 100-message regression dataset through the full pipeline (offline,
MockLLMClient) and enforces the architecture's success metrics:

    Domain Accuracy    >= 95%
    Intent Accuracy    >= 95%
    Category Accuracy  >= 95%
    Avg latency        <  1000ms  (local processing target)
"""

import pytest

from openclaw.tests.regression.report import run_regression


@pytest.fixture(scope="module")
def report():
    return run_regression()


def test_domain_accuracy(report):
    assert report.domain_accuracy >= 0.95, report.render()


def test_intent_accuracy(report):
    assert report.intent_accuracy >= 0.95, report.render()


def test_category_accuracy(report):
    assert report.category_accuracy >= 0.95, report.render()


def test_processing_under_one_second(report):
    assert report.avg_latency_ms < 1000, f"Avg latency {report.avg_latency_ms:.0f}ms exceeds 1s target"
