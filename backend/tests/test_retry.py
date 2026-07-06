from types import SimpleNamespace
from app.services.jobs import retry_delay
def job(strategy,n,delay=10): return SimpleNamespace(retry_strategy=SimpleNamespace(value=strategy),attempt_count=n,retry_delay_seconds=delay)
def test_fixed(): assert retry_delay(job("fixed",4))==10
def test_linear(): assert retry_delay(job("linear",4))==40
def test_exponential_and_cap():
    assert retry_delay(job("exponential",4))==80
    assert retry_delay(job("exponential",20))==86400
