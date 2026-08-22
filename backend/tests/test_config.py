from proofpay.config import Settings


def test_qwen_without_key_falls_back_to_deterministic():
    """A missing credential degrades quality; it must not break the pipeline."""
    settings = Settings(receipt_extractor="qwen", dashscope_api_key=None)

    assert settings.effective_receipt_extractor() == "deterministic"


def test_qwen_with_key_is_used():
    settings = Settings(receipt_extractor="qwen", dashscope_api_key="sk-test")

    assert settings.effective_receipt_extractor() == "qwen"
